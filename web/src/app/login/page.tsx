import { LoginForm } from "@/components/login-form"
import WarpLoader from "@/components/warp-loader"

export default function LoginPage() {
  return (
    <main className="relative flex min-h-svh items-center justify-center overflow-hidden bg-[#050507] px-6 text-white">
      <div className="pointer-events-none absolute inset-0">
        <WarpLoader />
      </div>
      {/* Stars fade out towards the middle, so the form sits in calm space instead of on a box. */}
      <div aria-hidden className="pointer-events-none absolute inset-0"
        style={{ background: "radial-gradient(ellipse 34rem 28rem at center, #050507 0%, rgba(5,5,7,.85) 40%, rgba(5,5,7,0) 75%)" }} />
      <div className="relative z-10 w-full max-w-sm">
        <LoginForm />
      </div>
    </main>
  )
}
