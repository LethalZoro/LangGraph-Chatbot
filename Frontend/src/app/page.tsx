"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import TypingDots from "@/components/TypingDots";

// Add Welcome Message Component
function WelcomeMessage() {
  return (
    <div className="text-center text-gray-500">
      <h2 className="text-2xl font-bold mb-2">Hi I am your personal Chatbot</h2>
      <p className="text-lg">How can I assist you?</p>
    </div>
  );
}

export default function Chatbot() {
  const [message, setMessage] = useState("");
  const [chatHistory, setChatHistory] = useState<{ user: string; bot: string | React.ReactNode }[]>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatHistory]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim()) return;

    // Add user message and temporary bot response
    setChatHistory(prev => [...prev, { user: message, bot: <TypingDots /> }]);
    setMessage("");

    // Simulate bot response
    setTimeout(() => {
      setChatHistory(prev => [
        ...prev.slice(0, -1),
        { user: message, bot: "Here is your response" }
      ]);
    }, 1000);
  };

  return (
    <div className="flex flex-col border p-4 rounded-lg max-w-[1080px] h-[90vh] mx-auto mt-12 justify-between">
      <div ref={scrollRef} className="overflow-y-auto scrollBar flex-1">
        {/* Show WelcomeMessage when no chat history */}
        {chatHistory.length === 0 ? (
          <div className="h-full flex justify-center items-center">
            <WelcomeMessage />
          </div>
        ) : (
          chatHistory.map((chat, index) => (
            <div key={index} className="my-4">
              <div className="border p-4 rounded-lg bg-gray-100 w-fit max-w-[70%] pe-8 ml-auto my-3">
                <p className="text-black font-bold">{chat.user}</p>
              </div>
              <div className="border p-4 rounded-lg bg-white w-fit max-w-[80%] pe-8 my-3">
                {typeof chat.bot === "string" ? (
                  <ReactMarkdown>{chat.bot}</ReactMarkdown>
                ) : (
                  chat.bot
                )}
              </div>
            </div>
          ))
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex gap-[1%]">
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          className="border border-gray-400 p-2 w-[74%] md:w-[89%] mt-2 rounded-lg"
          placeholder="Type your message..."
        />
        <button
          type="submit"
          className="bg-black text-white p-2 mt-2 w-[25%] md:w-[10%] rounded-lg"
        >
          Send
        </button>
      </form>
    </div>
  );
}