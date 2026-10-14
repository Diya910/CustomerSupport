import React from 'react';
import { motion } from 'framer-motion';

interface ThinkingDotsProps {
  agentThinking?: string | null;
}

const dotVariants = {
  initial: { opacity: 0.3 },
  animate: { opacity: 1 },
};

const dotTransition = (delay: number) => ({
  duration: 0.4,
  repeat: Infinity,
  repeatType: 'reverse' as const,
  delay,
});

export const ThinkingDots: React.FC<ThinkingDotsProps> = ({ agentThinking }) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -5 }}
      className="flex items-center gap-1.5 py-2"
    >
      <span className="text-sm text-gray-600 font-medium">
        {agentThinking || 'Thinking'}
      </span>
      <span className="flex items-center gap-0.5">
        <motion.span
          variants={dotVariants}
          initial="initial"
          animate="animate"
          transition={dotTransition(0)}
          className="w-1 h-1 bg-blue-500 rounded-full"
        />
        <motion.span
          variants={dotVariants}
          initial="initial"
          animate="animate"
          transition={dotTransition(0.15)}
          className="w-1 h-1 bg-blue-500 rounded-full"
        />
        <motion.span
          variants={dotVariants}
          initial="initial"
          animate="animate"
          transition={dotTransition(0.3)}
          className="w-1 h-1 bg-blue-500 rounded-full"
        />
      </span>
    </motion.div>
  );
};
