"use client"

import { useState } from "react"
import { Package, Menu, X } from "lucide-react"
import { Button } from "@/components/ui/button"

const navLinks = [
  { label: "Features", href: "#features" },
  { label: "How It Works", href: "#how-it-works" },
  { label: "Integrations", href: "#integrations" },
  { label: "Docs", href: "#docs" },
]

export function Header() {
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <header className="fixed top-0 left-0 right-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        <a href="#" className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <Package className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="text-lg font-semibold text-foreground">ShipAgent</span>
        </a>

        <nav className="hidden items-center gap-8 md:flex">
          {navLinks.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="hidden items-center gap-3 md:flex">
          <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-foreground">
            Sign In
          </Button>
          <Button size="sm" className="bg-primary text-primary-foreground hover:bg-primary/90">
            Get Started
          </Button>
        </div>

        <button
          type="button"
          className="text-muted-foreground md:hidden"
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label="Toggle menu"
        >
          {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {mobileOpen && (
        <div className="border-t border-border/50 bg-background px-6 py-4 md:hidden">
          <nav className="flex flex-col gap-4">
            {navLinks.map((link) => (
              <a
                key={link.label}
                href={link.href}
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                onClick={() => setMobileOpen(false)}
              >
                {link.label}
              </a>
            ))}
            <div className="flex flex-col gap-2 pt-2">
              <Button variant="ghost" size="sm" className="justify-start text-muted-foreground">
                Sign In
              </Button>
              <Button size="sm" className="bg-primary text-primary-foreground">
                Get Started
              </Button>
            </div>
          </nav>
        </div>
      )}
    </header>
  )
}
