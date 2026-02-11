import { ArrowDown } from "lucide-react"

const steps = [
  {
    number: "01",
    title: "Describe Your Shipment",
    description:
      'Type a plain-English command like "Ship all California orders from today\'s spreadsheet using UPS Ground."',
    code: `shipagent "Ship all CA orders\nfrom orders.xlsx\nusing UPS Ground"`,
  },
  {
    number: "02",
    title: "Automatic Data Extraction",
    description:
      "ShipAgent identifies your data source, parses the file, and uses an LLM to map columns to the carrier payload schema.",
    code: `Source: orders.xlsx (47 rows)\nMapping: name → ship_to.name\n         addr → ship_to.address\n         zip  → ship_to.postal_code`,
  },
  {
    number: "03",
    title: "Validate & Preview",
    description:
      "Every address is validated via the UPS API. Review cost estimates and shipment details before you commit.",
    code: `Validated: 47/47 addresses ✓\nEstimated cost: $342.18\nService: UPS Ground (3-5 days)`,
  },
  {
    number: "04",
    title: "Execute & Write Back",
    description:
      "Labels are created in batch with full crash recovery. Tracking numbers are written back to your source file automatically.",
    code: `Batch complete: 47/47 ✓\n1Z999AA10123456784 → Row 1\n1Z999AA10123456785 → Row 2\n...\nSource updated with tracking IDs`,
  },
]

export function HowItWorks() {
  return (
    <section id="how-it-works" className="border-y border-border bg-card/30 py-24 md:py-32">
      <div className="mx-auto max-w-7xl px-6">
        <div className="mb-16 text-center">
          <p className="mb-3 text-sm font-medium uppercase tracking-wider text-primary">
            Workflow
          </p>
          <h2 className="text-balance text-3xl font-bold text-foreground md:text-4xl">
            From words to shipments in four steps
          </h2>
        </div>

        <div className="grid gap-8 lg:grid-cols-2">
          {steps.map((step, i) => (
            <div key={step.number} className="flex flex-col gap-4">
              <div className="flex items-start gap-4">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-primary/30 font-mono text-sm font-bold text-primary">
                  {step.number}
                </span>
                <div>
                  <h3 className="mb-1 text-lg font-semibold text-foreground">{step.title}</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    {step.description}
                  </p>
                </div>
              </div>
              <div className="ml-14 rounded-lg border border-border bg-background p-4 font-mono text-xs leading-relaxed text-muted-foreground">
                <pre className="whitespace-pre-wrap">{step.code}</pre>
              </div>
              {i < steps.length - 1 && i % 2 === 1 && (
                <div className="hidden items-center justify-center py-2 lg:flex">
                  <ArrowDown className="h-5 w-5 text-muted-foreground/40" />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
