/**
 * ShipAgent Web Interface
 *
 * Root application component that will contain command input,
 * progress display, preview grid, and label management.
 */
function App() {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border bg-card">
        <div className="container mx-auto px-4 py-4">
          <h1 className="text-2xl font-bold text-foreground">
            ShipAgent
          </h1>
          <p className="text-sm text-muted-foreground">
            Natural language interface for batch shipment processing
          </p>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        <div className="rounded-lg border border-border bg-card p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-card-foreground">
            Command Input
          </h2>
          <p className="text-muted-foreground">
            Enter a natural language command to process shipments.
            For example: &quot;Ship all California orders using UPS Ground&quot;
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
