'use client';

import { motion } from 'framer-motion';
import { Shield, Zap, Eye, Lock } from 'lucide-react';

const stats = [
  { label: 'Model Accuracy', value: '94%+' },
  { label: 'Avg. Analysis Time', value: '<2s' },
  { label: 'GPU Accelerated', value: 'RTX' },
  { label: 'Formats Supported', value: '10+' },
];

const features = [
  { icon: <Shield size={18} />, text: 'ViT-based detection model' },
  { icon: <Zap size={18} />, text: 'CUDA GPU acceleration' },
  { icon: <Eye size={18} />, text: 'Facial heatmap analysis' },
  { icon: <Lock size={18} />, text: 'Runs 100% locally' },
];

export default function Hero({ onStartClick }: { onStartClick: () => void }) {
  return (
    <section className="relative min-h-screen flex flex-col items-center justify-center pt-16 overflow-hidden">
      {/* Background effects */}
      <div className="absolute inset-0 bg-grid-pattern opacity-100" />
      <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-accent-purple opacity-5 blur-[100px] pointer-events-none" />
      <div className="absolute top-1/2 right-0 w-[400px] h-[400px] rounded-full bg-accent-cyan opacity-5 blur-[80px] pointer-events-none" />

      <div className="relative z-10 max-w-5xl mx-auto px-4 text-center">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full glass border border-accent-purple/30 text-sm text-accent-purple-light mb-8">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-purple opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-purple" />
            </span>
            Powered by State-of-the-Art AI
          </div>

          {/* Heading */}
          <h1 className="text-5xl sm:text-7xl font-black tracking-tight mb-6 leading-tight">
            Detect{' '}
            <span className="text-gradient-main">Deepfakes</span>
            <br />
            Instantly
          </h1>

          <p className="text-xl text-gray-400 max-w-2xl mx-auto mb-10 leading-relaxed">
            Upload any image or video and our AI will analyze it in seconds — revealing
            manipulation probability, facial inconsistencies, and a detailed heatmap.
          </p>

          {/* Feature pills */}
          <div className="flex flex-wrap justify-center gap-3 mb-10">
            {features.map((f, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.3 + i * 0.1 }}
                className="flex items-center gap-2 px-3 py-1.5 rounded-full glass text-sm text-gray-300"
              >
                <span className="text-accent-purple">{f.icon}</span>
                {f.text}
              </motion.div>
            ))}
          </div>

          {/* CTA */}
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={onStartClick}
            className="px-8 py-4 rounded-2xl text-white font-bold text-lg relative overflow-hidden group glow-purple"
            style={{ background: 'linear-gradient(135deg, #8b5cf6, #06b6d4)' }}
          >
            <span className="relative z-10">Start Analyzing Now</span>
            <div className="absolute inset-0 bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity" />
          </motion.button>

          <p className="mt-4 text-sm text-gray-500">
            Free • No sign-up required • Max 500MB
          </p>
        </motion.div>

        {/* Stats */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, duration: 0.6 }}
          className="mt-20 grid grid-cols-2 sm:grid-cols-4 gap-4"
        >
          {stats.map((s, i) => (
            <div key={i} className="glass rounded-2xl p-5 text-center">
              <div className="text-3xl font-black text-gradient-main">{s.value}</div>
              <div className="text-sm text-gray-400 mt-1">{s.label}</div>
            </div>
          ))}
        </motion.div>
      </div>

      {/* Scroll indicator */}
      <motion.div
        animate={{ y: [0, 8, 0] }}
        transition={{ duration: 2, repeat: Infinity }}
        className="absolute bottom-8 left-1/2 -translate-x-1/2 text-gray-600"
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 5v14M5 12l7 7 7-7" />
        </svg>
      </motion.div>
    </section>
  );
}
