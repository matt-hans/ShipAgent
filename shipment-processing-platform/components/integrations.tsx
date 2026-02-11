import { FileSpreadsheet, Database, ShoppingBag, FileText } from "lucide-react"

const sources = [
  {
    icon: FileSpreadsheet,
    name: "Excel / CSV",
    description: "Import .xlsx and .csv files with automatic header detection and column mapping.",
    tags: [".xlsx", ".csv"],
  },
  {
    icon: Database,
    name: "PostgreSQL / MySQL",
    description: "Connect directly to your database and query shipment data with SQL or natural language.",
    tags: ["PostgreSQL", "MySQL"],
  },
  {
    icon: ShoppingBag,
    name: "Shopify",
    description: "Pull unfulfilled orders from your Shopify store and ship them in batch.",
    tags: ["REST API", "Orders"],
  },
  {
    icon: FileText,
    name: "Custom Sources",
    description: "Build custom connectors with the plugin API. JSON, XML, or any structured format.",
    tags: ["JSON", "XML", "API"],
  },
]

export function Integrations() {
  return (
    <section id="integrations" className="py-24 md:py-32">
      <div className="mx-auto max-w-7xl px-6">
        <div className="mb-16 text-center">
          <p className="mb-3 text-sm font-medium uppercase tracking-wider text-primary">
            Integrations
          </p>
          <h2 className="text-balance text-3xl font-bold text-foreground md:text-4xl">
            Connect to your data, wherever it lives
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-muted-foreground">
            ShipAgent reads from multiple data sources and writes tracking information back automatically.
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {sources.map((source) => (
            <div
              key={source.name}
              className="group flex flex-col rounded-xl border border-border bg-card p-6 transition-colors hover:border-primary/30"
            >
              <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                <source.icon className="h-5 w-5 text-primary" />
              </div>
              <h3 className="mb-2 font-semibold text-foreground">{source.name}</h3>
              <p className="mb-4 flex-1 text-sm leading-relaxed text-muted-foreground">
                {source.description}
              </p>
              <div className="flex flex-wrap gap-2">
                {source.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-muted-foreground"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
