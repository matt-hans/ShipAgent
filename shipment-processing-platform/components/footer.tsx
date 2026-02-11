import { Package } from "lucide-react"

const footerLinks = {
  Product: ["Features", "Integrations", "Pricing", "Changelog"],
  Resources: ["Documentation", "API Reference", "Examples", "Community"],
  Company: ["About", "Blog", "Careers", "Contact"],
  Legal: ["Privacy", "Terms", "License"],
}

export function Footer() {
  return (
    <footer className="border-t border-border bg-card/50">
      <div className="mx-auto max-w-7xl px-6 py-16">
        <div className="grid gap-12 md:grid-cols-5">
          <div className="md:col-span-1">
            <a href="#" className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
                <Package className="h-4 w-4 text-primary-foreground" />
              </div>
              <span className="text-lg font-semibold text-foreground">ShipAgent</span>
            </a>
            <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
              AI-powered batch shipment processing. Describe it in English, ship it in seconds.
            </p>
          </div>

          {Object.entries(footerLinks).map(([title, links]) => (
            <div key={title}>
              <p className="mb-4 text-sm font-semibold text-foreground">{title}</p>
              <ul className="flex flex-col gap-3">
                {links.map((link) => (
                  <li key={link}>
                    <a
                      href="#"
                      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {link}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-border pt-8 md:flex-row">
          <p className="text-xs text-muted-foreground">
            {"2026 ShipAgent. MIT License. Open source on GitHub."}
          </p>
          <div className="flex gap-6">
            <a href="#" className="text-xs text-muted-foreground transition-colors hover:text-foreground">
              GitHub
            </a>
            <a href="#" className="text-xs text-muted-foreground transition-colors hover:text-foreground">
              Discord
            </a>
            <a href="#" className="text-xs text-muted-foreground transition-colors hover:text-foreground">
              Twitter
            </a>
          </div>
        </div>
      </div>
    </footer>
  )
}
