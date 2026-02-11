import {
  MessageSquare,
  FileSpreadsheet,
  Truck,
  Layers,
  Columns3,
  Eye,
  RotateCcw,
  ArrowLeftRight,
} from "lucide-react"

const features = [
  {
    icon: MessageSquare,
    title: "Natural Language Commands",
    description:
      "Describe what you want to ship in plain English. No complex forms, no manual data entry.",
  },
  {
    icon: FileSpreadsheet,
    title: "Multiple Data Sources",
    description:
      "Import from CSV, Excel (.xlsx), PostgreSQL/MySQL databases, or Shopify stores.",
  },
  {
    icon: Truck,
    title: "UPS Integration",
    description:
      "Full API coverage for shipping, rating, address validation, and label generation.",
  },
  {
    icon: Layers,
    title: "Batch Processing",
    description:
      "Process hundreds of shipments in a single run with detailed per-row audit logging.",
  },
  {
    icon: Columns3,
    title: "Column Mapping",
    description:
      "LLM automatically generates source-to-payload field mappings from your data headers.",
  },
  {
    icon: Eye,
    title: "Preview Mode",
    description:
      "Review cost estimates and shipment details before committing to execution.",
  },
  {
    icon: RotateCcw,
    title: "Crash Recovery",
    description:
      "Resume interrupted batches from exactly where they stopped. Never lose progress.",
  },
  {
    icon: ArrowLeftRight,
    title: "Write-Back",
    description:
      "Automatically update tracking numbers and label URLs back into your source data.",
  },
]

export function Features() {
  return (
    <section id="features" className="py-24 md:py-32">
      <div className="mx-auto max-w-7xl px-6">
        <div className="mb-16 text-center">
          <p className="mb-3 text-sm font-medium uppercase tracking-wider text-primary">
            Capabilities
          </p>
          <h2 className="text-balance text-3xl font-bold text-foreground md:text-4xl">
            Everything you need to automate shipping
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-muted-foreground">
            From parsing your intent to writing back tracking numbers, ShipAgent handles the entire
            lifecycle of batch shipment processing.
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((feature) => (
            <div
              key={feature.title}
              className="group rounded-xl border border-border bg-card p-6 transition-colors hover:border-primary/30 hover:bg-card/80"
            >
              <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                <feature.icon className="h-5 w-5 text-primary" />
              </div>
              <h3 className="mb-2 font-semibold text-foreground">{feature.title}</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">{feature.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
