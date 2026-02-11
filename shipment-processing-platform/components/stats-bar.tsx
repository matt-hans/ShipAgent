const stats = [
  { value: "10x", label: "Faster than manual processing" },
  { value: "99.8%", label: "Address validation accuracy" },
  { value: "500+", label: "Shipments per batch" },
  { value: "0", label: "Lost shipments with crash recovery" },
]

export function StatsBar() {
  return (
    <section className="border-y border-border bg-card/50">
      <div className="mx-auto grid max-w-7xl grid-cols-2 divide-x divide-border md:grid-cols-4">
        {stats.map((stat) => (
          <div key={stat.label} className="flex flex-col items-center gap-1 px-6 py-8 text-center">
            <span className="text-3xl font-bold text-foreground md:text-4xl">{stat.value}</span>
            <span className="text-xs text-muted-foreground md:text-sm">{stat.label}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
