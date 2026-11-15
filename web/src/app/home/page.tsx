import { redirect } from "next/navigation"

/** The upload now lives on the start page, below the hero. Old links land there. */
export default function Home() {
  redirect("/#upload")
}
