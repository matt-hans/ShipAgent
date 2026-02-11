"use client"

import { useEffect, useState } from "react"

const lines = [
  { type: "prompt" as const, text: '$ shipagent "Ship all California orders from today\'s spreadsheet using UPS Ground"' },
  { type: "info" as const, text: "Parsing natural language command..." },
  { type: "info" as const, text: "Detected source: orders_2026-02-10.xlsx" },
  { type: "info" as const, text: "Filter: state = CA | Service: UPS Ground" },
  { type: "success" as const, text: "Column mapping generated (12 fields matched)" },
  { type: "info" as const, text: "Validating 47 shipments against UPS schema..." },
  { type: "success" as const, text: "All addresses validated" },
  { type: "info" as const, text: "Processing batch [====================] 47/47" },
  { type: "success" as const, text: "47 labels created | Tracking numbers written back to source" },
]

export function TerminalDemo() {
  const [visibleLines, setVisibleLines] = useState(0)

  useEffect(() => {
    if (visibleLines < lines.length) {
      const timeout = setTimeout(() => {
        setVisibleLines((prev) => prev + 1)
      }, 600)
      return () => clearTimeout(timeout)
    }
  }, [visibleLines])

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-2xl shadow-primary/5">
      {/* Title bar */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <div className="flex gap-1.5">
          <div className="h-3 w-3 rounded-full bg-[#ff5f57]" />
          <div className="h-3 w-3 rounded-full bg-[#ffbd2e]" />
          <div className="h-3 w-3 rounded-full bg-[#28c840]" />
        </div>
        <span className="ml-2 text-xs text-muted-foreground">shipagent -- terminal</span>
      </div>

      {/* Terminal body */}
      <div className="p-5 font-mono text-sm leading-relaxed md:p-6">
        {lines.slice(0, visibleLines).map((line, i) => (
          <div key={i} className="mb-1">
            {line.type === "prompt" && (
              <span className="text-foreground">{line.text}</span>
            )}
            {line.type === "info" && (
              <span className="text-muted-foreground">
                {"  "}
                {line.text}
              </span>
            )}
            {line.type === "success" && (
              <span className="text-primary">
                {"  "}
                {"✓ "}
                {line.text}
              </span>
            )}
          </div>
        ))}
        {visibleLines < lines.length && (
          <span className="inline-block h-4 w-2 animate-pulse bg-primary/70" />
        )}
      </div>
    </div>
  )
}
