/**
 * ShipAgent Web Interface
 *
 * Root application component that will contain command input,
 * progress display, preview grid, and label management.
 */
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"

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
        <Card>
          <CardHeader>
            <CardTitle>Command Input</CardTitle>
            <CardDescription>
              Enter a natural language command to process shipments.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2">
              <Input
                placeholder='Ship all California orders using UPS Ground'
                className="flex-1"
              />
              <Button>Submit</Button>
            </div>
            <div className="mt-4 space-y-2">
              <p className="text-sm text-muted-foreground">
                Processing shipments...
              </p>
              <Progress value={33} />
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  )
}

export default App
