"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

interface Msg {
  role: "user" | "assistant";
  text: string;
}

// Готові підказки — щоб журі/диспетчер одразу бачили, що питати.
const SUGGESTIONS = [
  "Кого рятувати першим і що везти?",
  "Які об'єкти не переживуть найближчу годину?",
  "Склади план на 2 генератори",
];

export function CopilotPanel() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function ask(q: string) {
    const question = q.trim();
    if (!question || loading) return;
    setMessages((m) => [...m, { role: "user", text: question }]);
    setInput("");
    setLoading(true);
    try {
      const res = await api.copilot(question);
      setMessages((m) => [...m, { role: "assistant", text: res.answer }]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", text: "Помилка зв'язку з копілотом. Спробуй ще раз." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {/* Плаваюча кнопка (над нижньою навігацією на мобільному) */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed z-[75] bottom-16 lg:bottom-6 right-4 lg:right-6 flex items-center gap-2 bg-primary text-on-primary font-semibold px-4 py-3 rounded-full shadow-[0_0_20px_rgba(77,142,255,0.5)] hover:scale-105 active:scale-95 transition-transform"
          aria-label="AI-копілот"
        >
          <i className="material-symbols-outlined">smart_toy</i>
          <span className="hidden sm:inline">AI-копілот</span>
        </button>
      )}

      {open && (
        <div className="fixed z-[80] bottom-16 lg:bottom-6 right-4 lg:right-6 w-[calc(100vw-2rem)] sm:w-[400px] max-h-[70vh] flex flex-col bg-surface-container-high/98 backdrop-blur-xl border border-primary/25 rounded-2xl shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-white/10 bg-[#0e1826]">
            <i className="material-symbols-outlined text-primary">smart_toy</i>
            <div className="flex-1">
              <div className="font-bold text-[14px] text-on-surface">AI-копілот диспетчера</div>
              <div className="text-[11px] text-on-surface-variant">
                Відповідає на живому стані міста
              </div>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-on-surface-variant hover:text-on-surface p-1"
              aria-label="Закрити"
            >
              <i className="material-symbols-outlined text-[20px]">close</i>
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3 min-h-[200px]">
            {messages.length === 0 && (
              <div className="flex flex-col gap-2">
                <p className="text-[13px] text-on-surface-variant">
                  Спитай про стан міста або попроси план дій:
                </p>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => ask(s)}
                    className="text-left text-[13px] bg-surface-bright/10 hover:bg-primary-container/20 border border-white/5 rounded-lg px-3 py-2 transition-colors text-on-surface"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            {messages.map((m, i) => (
              <div
                key={i}
                className={`text-[13px] leading-relaxed rounded-xl px-3 py-2 max-w-[90%] whitespace-pre-wrap ${
                  m.role === "user"
                    ? "self-end bg-primary text-on-primary"
                    : "self-start bg-surface-bright/10 text-on-surface border border-white/5"
                }`}
              >
                {m.text}
              </div>
            ))}
            {loading && (
              <div className="self-start text-[13px] text-on-surface-variant animate-pulse px-3 py-2">
                Копілот аналізує стан міста…
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              ask(input);
            }}
            className="flex gap-2 p-3 border-t border-white/10"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Напиши питання…"
              className="flex-1 bg-surface-dim/50 border border-white/10 rounded-lg px-3 py-2 text-[13px] text-on-surface outline-none focus:border-primary/50"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="bg-primary text-on-primary rounded-lg px-3 disabled:opacity-40 transition-opacity"
              aria-label="Надіслати"
            >
              <i className="material-symbols-outlined text-[20px]">send</i>
            </button>
          </form>
        </div>
      )}
    </>
  );
}
