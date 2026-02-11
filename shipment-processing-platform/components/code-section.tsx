"use client"

import { useState } from "react"
import { Copy, Check } from "lucide-react"
import { Button } from "@/components/ui/button"

const codeExamples = [
  {
    label: "Quick Start",
    language: "bash",
    code: `# Install ShipAgent
pip install shipagent

# Set your UPS credentials
export UPS_CLIENT_ID="your-client-id"
export UPS_CLIENT_SECRET="your-client-secret"
export OPENAI_API_KEY="your-api-key"

# Run your first batch
shipagent "Ship all orders from orders.csv using UPS Ground"`,
  },
  {
    label: "Python SDK",
    language: "python",
    code: `from shipagent import ShipAgent

agent = ShipAgent()

# Natural language command
result = agent.run(
    "Ship California orders from orders.xlsx "
    "using UPS Ground, skip rows with missing zip codes"
)

print(f"Shipped: {result.success_count}/{result.total_count}")
print(f"Tracking: {result.tracking_numbers}")`,
  },
  {
    label: "Config File",
    language: "yaml",
    code: `# shipagent.yaml
carrier:
  name: ups
  service: ground
  account: "YOUR_ACCOUNT"

source:
  type: excel
  path: ./orders.xlsx
  filters:
    state: CA

options:
  preview: true
  crash_recovery: true
  write_back: true`,
  },
]

export function CodeSection() {
  const [activeTab, setActiveTab] = useState(0)
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(codeExamples[activeTab].code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <section id="docs" className="border-y border-border bg-card/30 py-24 md:py-32">
      <div className="mx-auto max-w-7xl px-6">
        <div className="grid items-start gap-12 lg:grid-cols-2 lg:gap-16">
          <div>
            <p className="mb-3 text-sm font-medium uppercase tracking-wider text-primary">
              Developer Experience
            </p>
            <h2 className="text-balance text-3xl font-bold text-foreground md:text-4xl">
              Built for developers, powered by AI
            </h2>
            <p className="mt-4 text-muted-foreground">
              Install with pip, configure your carriers, and start shipping. The CLI, Python SDK,
              and YAML config give you full control over every aspect of the pipeline.
            </p>

            <div className="mt-8 flex flex-col gap-4">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                  {"P"}
                </span>
                <div>
                  <p className="text-sm font-medium text-foreground">Python 3.12+</p>
                  <p className="text-sm text-muted-foreground">
                    Modern Python with type hints and async support throughout.
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                  {"R"}
                </span>
                <div>
                  <p className="text-sm font-medium text-foreground">React 19 Dashboard</p>
                  <p className="text-sm text-muted-foreground">
                    Real-time batch monitoring with live progress updates.
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                  {"M"}
                </span>
                <div>
                  <p className="text-sm font-medium text-foreground">MIT Licensed</p>
                  <p className="text-sm text-muted-foreground">
                    Open source and free for commercial use. Contribute on GitHub.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="overflow-hidden rounded-xl border border-border bg-background">
            {/* Tab bar */}
            <div className="flex items-center justify-between border-b border-border px-1">
              <div className="flex">
                {codeExamples.map((example, i) => (
                  <button
                    type="button"
                    key={example.label}
                    onClick={() => setActiveTab(i)}
                    className={`px-4 py-3 text-xs font-medium transition-colors ${
                      activeTab === i
                        ? "border-b-2 border-primary text-foreground"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {example.label}
                  </button>
                ))}
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopy}
                className="mr-2 text-muted-foreground hover:text-foreground"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
              </Button>
            </div>

            {/* Code */}
            <div className="p-5 md:p-6">
              <pre className="overflow-x-auto font-mono text-xs leading-relaxed text-muted-foreground md:text-sm">
                <code>{codeExamples[activeTab].code}</code>
              </pre>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
