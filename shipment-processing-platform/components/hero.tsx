"use client"

import { ArrowRight, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { TerminalDemo } from "@/components/terminal-demo"

export function Hero() {
  return (
    <section className="relative overflow-hidden pt-32 pb-20 md:pt-44 md:pb-32">
      {/* Background glow */}
      <div className="pointer-events-none absolute top-0 left-1/2 -translate-x-1/2">
        <div className="h-[600px] w-[800px] rounded-full bg-primary/8 blur-[120px]" />
      </div>

      <div className="relative mx-auto max-w-7xl px-6">
        <div className="flex flex-col items-center text-center">
          {/* Badge */}
          <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-border bg-secondary px-4 py-1.5">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            <span className="text-xs font-medium text-muted-foreground">
              Natural Language Batch Processing
            </span>
          </div>

          {/* Headline */}
          <h1 className="max-w-4xl text-balance text-4xl font-bold tracking-tight text-foreground md:text-6xl lg:text-7xl">
            Ship hundreds of orders with a single sentence
          </h1>

          {/* Sub */}
          <p className="mt-6 max-w-2xl text-pretty text-lg text-muted-foreground md:text-xl">
            Describe what you want to ship in plain English. ShipAgent parses your intent, 
            validates against carrier schemas, and executes batch shipments with full audit trails.
          </p>

          {/* CTA */}
          <div className="mt-10 flex flex-col items-center gap-4 sm:flex-row">
            <Button size="lg" className="bg-primary text-primary-foreground hover:bg-primary/90">
              Get Started Free
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
            <Button
              size="lg"
              variant="outline"
              className="border-border text-foreground hover:bg-secondary bg-transparent"
            >
              View Documentation
            </Button>
          </div>

          {/* Terminal Demo */}
          <div className="mt-16 w-full max-w-3xl">
            <TerminalDemo />
          </div>
        </div>
      </div>
    </section>
  )
}
