import { ChevronDown } from "lucide-react"

import { ScrollScene } from "@/components/scroll-scene"
import { UploadPanel } from "@/components/upload-panel"

export default function Page() {
  return (
    <ScrollScene>
      <main>
        <section
          className="relative flex min-h-svh flex-col items-center justify-center px-6 text-center"
          style={{ opacity: "calc(1 - var(--p) * 1.4)", transform: "translateY(calc(var(--p) * -48px))" }}
        >
          <p className="text-[11px] font-medium uppercase tracking-[0.32em] text-white/50">Adaptive CSV analytics</p>
          <h1 className="mt-5 text-[clamp(3.5rem,11vw,8.5rem)] font-bold leading-[0.95] tracking-[-0.045em]">
            Vision Quest
          </h1>
          <p className="mt-6 max-w-lg text-base text-white/60 sm:text-lg">
            Any CSV in. A dashboard that understands it, out.
          </p>
          <div className="absolute bottom-10 flex flex-col items-center gap-2 text-[11px] uppercase tracking-[0.28em] text-white/40">
            <span>Scroll</span>
            <ChevronDown className="size-4 animate-bounce" aria-hidden />
          </div>
        </section>

        <section
          id="upload"
          className="flex min-h-svh items-center justify-center px-6 py-24"
          style={{ opacity: "clamp(0, calc((var(--p) - 0.35) * 1.8), 1)", transform: "translateY(calc((1 - var(--p)) * 40px))" }}
        >
          <UploadPanel />
        </section>
      </main>
    </ScrollScene>
  )
}
