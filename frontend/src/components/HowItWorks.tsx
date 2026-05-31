'use client';

import { motion } from 'framer-motion';
import { Upload, Brain, BarChart2 } from 'lucide-react';

const steps = [
  {
    icon: <Upload size={28} />,
    title: 'Upload',
    description:
      'Drag and drop any image (JPG, PNG, WEBP) or video (MP4, MOV, MKV, WEBM). Max 500MB.',
    color: 'text-accent-purple',
    bg: 'bg-accent-purple/10 border-accent-purple/20',
  },
  {
    icon: <Brain size={28} />,
    title: 'AI Analysis',
    description:
      'Our ViT model detects facial artifacts, GAN fingerprints, and temporal inconsistencies using CUDA acceleration.',
    color: 'text-accent-cyan',
    bg: 'bg-accent-cyan/10 border-accent-cyan/20',
  },
  {
    icon: <BarChart2 size={28} />,
    title: 'Results',
    description:
      'Get instant results: fake probability, verdict badge, attention heatmap, and a frame-by-frame timeline for videos.',
    color: 'text-real-green',
    bg: 'bg-real-green/10 border-real-green/20',
  },
];

const techStack = [
  { name: 'Vision Transformer', detail: 'ViT deepfake model' },
  { name: 'MTCNN', detail: 'Face detection' },
  { name: 'Grad-CAM++', detail: 'Attention heatmaps' },
  { name: 'CUDA / RTX GPU', detail: 'GPU acceleration' },
  { name: 'FastAPI', detail: 'Backend API' },
  { name: 'Next.js 14', detail: 'Frontend' },
];

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="py-24 px-4">
      <div className="max-w-5xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-center mb-16"
        >
          <h2 className="text-4xl font-black mb-4">
            How It <span className="text-gradient-main">Works</span>
          </h2>
          <p className="text-gray-400 max-w-xl mx-auto">
            Three simple steps powered by state-of-the-art computer vision and deep learning.
          </p>
        </motion.div>

        <div className="grid md:grid-cols-3 gap-6 mb-16">
          {steps.map((step, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.15 }}
              className="glass rounded-3xl p-6 relative overflow-hidden group hover:border-white/10 transition-all"
            >
              <div className="absolute top-0 right-0 w-24 h-24 bg-gradient-radial from-white/5 to-transparent rounded-bl-full" />
              <div className={`w-14 h-14 rounded-2xl border flex items-center justify-center mb-5 ${step.bg} ${step.color}`}>
                {step.icon}
              </div>
              <div className="text-5xl font-black text-white/5 absolute top-4 right-5">
                {i + 1}
              </div>
              <h3 className="text-lg font-bold text-white mb-2">{step.title}</h3>
              <p className="text-sm text-gray-400 leading-relaxed">{step.description}</p>
            </motion.div>
          ))}
        </div>

        {/* Tech stack */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="glass rounded-3xl p-6"
        >
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4 text-center">
            Technology Stack
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {techStack.map((t, i) => (
              <div key={i} className="bg-surface/60 rounded-xl px-4 py-3 border border-border">
                <div className="text-sm font-semibold text-white">{t.name}</div>
                <div className="text-xs text-gray-500 mt-0.5">{t.detail}</div>
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  );
}
