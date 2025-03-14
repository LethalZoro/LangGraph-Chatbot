// app/page.tsx
import Chatbot from '@/components/Chatbot';

export default function Home() {
  return (
    <main className="container mx-auto p-4">
      <h1 className="text-3xl font-bold mb-8">Shipping Workflow Assistant</h1>
      <Chatbot />
    </main>
  );
}