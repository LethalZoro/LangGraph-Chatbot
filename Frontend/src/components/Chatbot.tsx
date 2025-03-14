// components/Chatbot.tsx
"use client";

import dynamic from 'next/dynamic';

const Chatbot = dynamic(
  () => import('./ChatbotInner'),
  { 
    ssr: false,
    loading: () => <div className="p-4 text-center text-gray-500">Loading chat interface...</div>
  }
);

export default Chatbot;