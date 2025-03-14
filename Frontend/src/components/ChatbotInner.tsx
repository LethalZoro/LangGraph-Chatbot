// components/ChatbotInner.tsx
"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import TypingDots from "@/components/TypingDots";
import { io, Socket } from "socket.io-client";

interface ChatMessage {
  type: 'user' | 'bot';
  content: string | React.ReactNode;
}

interface SessionData {
  session_id: string;
}

export default function ChatbotInner() {
  const [message, setMessage] = useState("");
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const socketRef = useRef<Socket | null>(null);

  useEffect(() => {
    // Client-side only check
    if (typeof window === 'undefined') return;

    // Change the connection line to:
    // Change the socket.io client connection to:
    socketRef.current = io("http://localhost:5000", {
        autoConnect: true,
        transports: ["websocket"],
        path: "/socket.io",  // Explicitly set path
        withCredentials: true,
        reconnectionAttempts: 3,
        reconnectionDelay: 3000,
    });

    const socket = socketRef.current;

    // Add these event listeners in useEffect
    socket.on("connect_error", (err) => {
        console.log("Connection Error:", err);
    });
    
    socket.on("connect_timeout", () => {
        console.log("Connection Timeout");
    });
    
    socket.on("reconnect_attempt", () => {
        console.log("Reconnection Attempt");
    });
    
    const handleSocketConnect = () => {
      console.log("Connected to WebSocket server");
    };

    const handleSessionCreated = (data: SessionData) => {
      console.log("New session created:", data.session_id);
      setSessionId(data.session_id);
    };

    const handleQuestion = (data: { question: string }) => {
      setIsTyping(true);
      setChatHistory(prev => [
        ...prev,
        { type: 'bot', content: data.question }
      ]);
    };

    const handleUpdate = (data: { response: string }) => {
      setIsTyping(false);
      setChatHistory(prev => [
        ...prev.slice(0, -1),
        { type: 'bot', content: data.response }
      ]);
    };

    const handleWorkflowComplete = (data: { state: any }) => {
      setIsTyping(false);
      setChatHistory(prev => [
        ...prev,
        { type: 'bot', content: "Workflow complete! Here's your final data:" },
        { type: 'bot', content: <pre>{JSON.stringify(data.state, null, 2)}</pre> }
      ]);
    };

    const handleError = (error: { error: string }) => {
      setIsTyping(false);
      setChatHistory(prev => [
        ...prev,
        { type: 'bot', content: `Error: ${error.error}` }
      ]);
    };

    socket.on("connect", handleSocketConnect);
    socket.on("session_created", handleSessionCreated);
    socket.on("question", handleQuestion);
    socket.on("update", handleUpdate);
    socket.on("workflow_complete", handleWorkflowComplete);
    socket.on("error", handleError);

    return () => {
      socket.off("connect", handleSocketConnect);
      socket.off("session_created", handleSessionCreated);
      socket.off("question", handleQuestion);
      socket.off("update", handleUpdate);
      socket.off("workflow_complete", handleWorkflowComplete);
      socket.off("error", handleError);
      socket.disconnect();
    };
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim() || !sessionId) return;

    // Add user message and typing indicator
    setChatHistory(prev => [
      ...prev,
      { type: 'user', content: message },
      { type: 'bot', content: <TypingDots /> }
    ]);

    // Send message to backend
    socketRef.current?.emit("user_response", {
      session_id: sessionId,
      response: message
    });

    setMessage("");
    setIsTyping(true);
  };

  return (
    <div className="flex flex-col border p-4 rounded-lg max-w-[1080px] h-[90vh] mx-auto mt-12 justify-between">
      <div ref={scrollRef} className="overflow-y-auto scrollBar flex-1">
        {chatHistory.map((message, index) => (
          <div key={index} className={`my-4 ${message.type === 'user' ? 'text-right' : ''}`}>
            <div className={`p-4 rounded-lg inline-block max-w-[80%] ${
              message.type === 'user' 
                ? 'bg-blue-100 ml-auto' 
                : 'bg-gray-100'
            }`}>
              {typeof message.content === 'string' ? (
                <ReactMarkdown >{message.content}</ReactMarkdown>
              ) : (
                message.content
              )}
            </div>
          </div>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2 mt-4">
        <input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          className="flex-1 border p-2 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="Type your message..."
          disabled={!sessionId || isTyping}
        />
        <button
          type="submit"
          className="bg-blue-500 text-white px-4 py-2 rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          disabled={!message || !sessionId || isTyping}
        >
          Send
        </button>
      </form>
    </div>
  );
}