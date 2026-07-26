"use client";

import { motion } from "framer-motion";
import { Construction } from "lucide-react";

export default function KubernetesPage() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5 }}
      >
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-white/[0.08] bg-gradient-to-br from-electric-500/20 to-purple-500/20">
          <Construction className="h-8 w-8 text-electric-400" />
        </div>
        <h1 className="mb-2 text-2xl font-bold tracking-tight text-white">Kubernetes</h1>
        <p className="text-sm text-white/40">This page is under development</p>
      </motion.div>
    </div>
  );
}
