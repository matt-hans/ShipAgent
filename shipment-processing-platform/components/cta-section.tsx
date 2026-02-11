import { ArrowRight, Package } from "lucide-react"
import { Button } from "@/components/ui/button"

export function CTASection() {
  return (
    <section className="py-24 md:py-32">
      <div className="mx-auto max-w-7xl px-6">
        <div className="relative overflow-hidden rounded-2xl border border-border bg-card px-8 py-16 text-center md:px-16 md:py-24">
          {/* Subtle glow */}
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="h-[300px] w-[500px] rounded-full bg-primary/6 blur-[100px]" />
          </div>

          <div className="relative">
            <h2 className="text-balance text-3xl font-bold text-foreground md:text-5xl">
              Stop copying tracking numbers by hand
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-muted-foreground md:text-lg">
              Join teams who have automated their shipping workflows with ShipAgent. 
              Install in minutes, ship hundreds of orders with a single command.
            </p>
            <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <Button size="lg" className="bg-primary text-primary-foreground hover:bg-primary/90">
                Get Started Free
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
              <Button
                size="lg"
                variant="outline"
                className="border-border text-foreground hover:bg-secondary bg-transparent"
              >
                Star on GitHub
              </Button>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
