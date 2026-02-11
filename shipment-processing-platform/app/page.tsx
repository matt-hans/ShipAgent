import { Header } from "@/components/header"
import { Hero } from "@/components/hero"
import { StatsBar } from "@/components/stats-bar"
import { Features } from "@/components/features"
import { HowItWorks } from "@/components/how-it-works"
import { Integrations } from "@/components/integrations"
import { CodeSection } from "@/components/code-section"
import { CTASection } from "@/components/cta-section"
import { Footer } from "@/components/footer"

export default function Home() {
  return (
    <main>
      <Header />
      <Hero />
      <StatsBar />
      <Features />
      <HowItWorks />
      <Integrations />
      <CodeSection />
      <CTASection />
      <Footer />
    </main>
  )
}
