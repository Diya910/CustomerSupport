import { useChatStore } from '../store/chatStore';

const MIN_SENTENCE_LENGTH = 20;
const MARKDOWN_STRIP = /[*#_`~>]/g;

// Sentinel stored in readyChunks when a chunk's fetch failed or produced no
// audio. Playback skips it instead of stalling on a never-arriving blob.
const FAILED_CHUNK = null;

class StreamingTtsService {
  private currentAudio: HTMLAudioElement | null = null;
  private currentObjectUrl: string | null = null;
  private lastProcessedLength = 0;
  private pendingText = '';
  private rafId: number | null = null;
  private aborted = false;
  private activeFetches: AbortController[] = [];

  // Ordered playback: each dispatched chunk gets a monotonic sequence number.
  // Fetches run in parallel but audio plays strictly in dispatch order, so a
  // chunk whose fetch resolves early never plays ahead of an earlier chunk.
  private dispatchSeq = 0;
  private nextToPlay = 0;
  private readyChunks = new Map<number, Blob | null>();
  private isPlaying = false;

  start() {
    this.stop();
    this.aborted = false;
    this.resetState();

    const state = useChatStore.getState();
    this.lastProcessedLength = state.currentMessage?.content.length || 0;

    this.startWatching();
  }

  stop() {
    this.aborted = true;
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    this.activeFetches.forEach((c) => c.abort());
    this.activeFetches = [];
    if (this.currentAudio) {
      this.currentAudio.onended = null;
      this.currentAudio.onerror = null;
      this.currentAudio.pause();
      this.currentAudio = null;
    }
    if (this.currentObjectUrl) {
      URL.revokeObjectURL(this.currentObjectUrl);
      this.currentObjectUrl = null;
    }
    this.resetState();
  }

  private resetState() {
    this.pendingText = '';
    this.lastProcessedLength = 0;
    this.isPlaying = false;
    this.dispatchSeq = 0;
    this.nextToPlay = 0;
    this.readyChunks.clear();
  }

  private startWatching() {
    const poll = () => {
      if (this.aborted) return;

      const state = useChatStore.getState();
      const content = state.currentMessage?.content || '';

      // The store calls clearMessageContent() mid-turn (e.g. the acknowledgement
      // is wiped before each tool's status_before event), resetting
      // currentMessage.content to ''. Detect that by a shrink and resync the
      // offset so we don't drop the start of the next (final-answer) segment.
      // Any not-yet-spoken buffer from the wiped segment is dropped with it,
      // matching what the UI shows.
      if (content.length < this.lastProcessedLength) {
        this.lastProcessedLength = 0;
        this.pendingText = '';
      }

      if (content.length > this.lastProcessedLength) {
        const newText = content.slice(this.lastProcessedLength);
        this.pendingText += newText;
        this.lastProcessedLength = content.length;
        this.extractAndDispatch(false);
      }

      // The websocket handler drains its token buffer into currentMessage.content
      // BEFORE clearing isStreaming/currentMessage, so by the time we observe
      // !isStreaming the loop above has already captured the complete final
      // answer into pendingText. We therefore just flush the remaining buffer —
      // we must NOT reconcile against the persisted conversation message, whose
      // length is a different baseline than lastProcessedLength (mixing the two
      // re-speaks the whole answer).
      if (!state.isStreaming) {
        this.extractAndDispatch(true);
        return;
      }

      this.rafId = requestAnimationFrame(poll);
    };
    this.rafId = requestAnimationFrame(poll);
  }

  private extractAndDispatch(flush: boolean) {
    const cleaned = this.pendingText.replace(MARKDOWN_STRIP, '').trim();

    if (flush) {
      if (cleaned.length > 0) {
        this.pendingText = '';
        this.dispatchTts(cleaned);
      }
      return;
    }

    let lastBoundary = -1;
    const matches = cleaned.matchAll(/[.!?][\s]/g);
    for (const m of matches) {
      if (m.index !== undefined && m.index >= MIN_SENTENCE_LENGTH - 1) {
        lastBoundary = m.index + m[0].length;
      }
    }

    if (lastBoundary === -1) {
      const endMatch = cleaned.match(/[.!?]$/);
      if (endMatch && endMatch.index !== undefined && endMatch.index >= MIN_SENTENCE_LENGTH - 1) {
        lastBoundary = cleaned.length;
      }
    }

    if (lastBoundary > 0) {
      const sentence = cleaned.slice(0, lastBoundary).trim();
      const rawConsumed = this.findRawOffset(this.pendingText, lastBoundary);
      this.pendingText = this.pendingText.slice(rawConsumed);
      if (sentence.length > 0) {
        this.dispatchTts(sentence);
      }
    }
  }

  private findRawOffset(raw: string, cleanedEnd: number): number {
    let cleanIdx = 0;
    let rawIdx = 0;
    while (rawIdx < raw.length && cleanIdx < cleanedEnd) {
      if (!MARKDOWN_STRIP.test(raw[rawIdx])) {
        cleanIdx++;
      }
      MARKDOWN_STRIP.lastIndex = 0;
      rawIdx++;
    }
    return rawIdx;
  }

  private dispatchTts(text: string) {
    if (this.aborted || !text.trim()) return;

    const seq = this.dispatchSeq++;
    const controller = new AbortController();
    this.activeFetches.push(controller);

    const settle = (value: Blob | null) => {
      this.activeFetches = this.activeFetches.filter((c) => c !== controller);
      if (this.aborted) return;
      this.readyChunks.set(seq, value);
      this.playNext();
    };

    const basePath = (import.meta as any).env.BASE_URL.replace(/\/$/, '');
    fetch(`${basePath}/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok) throw new Error('TTS fetch failed');
        return res.blob();
      })
      .then((blob) => {
        settle(blob && blob.size > 0 ? blob : FAILED_CHUNK);
      })
      .catch(() => {
        // Aborted fetches and genuine errors both resolve the slot so playback
        // of later chunks is never blocked waiting on this sequence number.
        settle(FAILED_CHUNK);
      });
  }

  private playNext() {
    if (this.isPlaying || this.aborted) return;

    // Strict in-order consumption: only play the chunk at nextToPlay. If it
    // isn't ready yet, wait — do NOT play a later chunk that resolved first.
    if (!this.readyChunks.has(this.nextToPlay)) return;

    const blob = this.readyChunks.get(this.nextToPlay) ?? FAILED_CHUNK;
    this.readyChunks.delete(this.nextToPlay);
    this.nextToPlay++;

    if (blob === FAILED_CHUNK) {
      // Skip a failed/empty chunk and immediately try the next one.
      this.playNext();
      return;
    }

    this.isPlaying = true;

    if (this.currentObjectUrl) {
      URL.revokeObjectURL(this.currentObjectUrl);
    }
    this.currentObjectUrl = URL.createObjectURL(blob);
    const audio = new Audio(this.currentObjectUrl);
    this.currentAudio = audio;

    const advance = () => {
      this.isPlaying = false;
      this.currentAudio = null;
      if (this.currentObjectUrl) {
        URL.revokeObjectURL(this.currentObjectUrl);
        this.currentObjectUrl = null;
      }
      if (!this.aborted) this.playNext();
    };

    audio.onended = advance;
    audio.onerror = advance;

    audio.play().catch(() => {
      // Autoplay rejection or decode failure — advance so the queue drains.
      advance();
    });
  }
}

export const streamingTts = new StreamingTtsService();
