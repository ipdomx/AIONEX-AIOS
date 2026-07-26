"use client";

import { motion } from "framer-motion";
import { Construction } from "lucide-react";

export default function EventsPage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
      <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.5 }}>
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-electric-500/20 to-purple-500/20 flex items-center justify-center border border-white/[0.08] mb-4 mx-auto">
          <Construction className="w-8 h-8 text-electric-400" />
        </div>
        <h1 className="text-2xl font-bold text-white tracking-tight mb-2">Events</h1>
        <p className="text-sm text-white/40">This page is under development</p>
      </motion.div>
    </div>
  );
}
