import React, { memo } from 'react';
import { Loader2, CheckCircle2 } from 'lucide-react';

export interface ToolStep {
  id: string;
  content: string;
  timestamp: number;
  type: 'progress' | 'success' | 'info' | 'error' | 'input';
  isStreaming?: boolean;
}

export interface LLMStream {
  isStreaming: boolean;
  content: string;
  llm_type: string;
}

interface ToolExecutionCardProps {
  toolName: string;
  toolDescription?: string;
  steps: ToolStep[];
  isExecuting: boolean;
  startTime?: number;
  llmStream?: LLMStream;
}

export const ToolExecutionCard: React.FC<ToolExecutionCardProps> = memo(({
  toolName,
  toolDescription,
  isExecuting,
}) => {
  return (
    <div className="mb-2 px-3 py-2 flex items-center gap-2.5 rounded-lg bg-gray-50 border border-gray-200">
      {isExecuting ? (
        <div className="w-5 h-5 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
          <Loader2 className="w-3 h-3 text-blue-600 animate-spin" />
        </div>
      ) : (
        <div className="w-5 h-5 rounded-full bg-green-100 flex items-center justify-center flex-shrink-0">
          <CheckCircle2 className="w-3 h-3 text-green-600" />
        </div>
      )}
      <div className="flex flex-col min-w-0">
        <span className="text-sm font-medium text-gray-700">{toolName}</span>
        {toolDescription && (
          <span className="text-xs text-gray-400 truncate max-w-xs">{toolDescription}</span>
        )}
      </div>
    </div>
  );
});

ToolExecutionCard.displayName = 'ToolExecutionCard';
