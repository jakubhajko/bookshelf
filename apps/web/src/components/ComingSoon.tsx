interface ComingSoonProps {
  title: string
  description: string
}

/** Placeholder for routes that exist (spec §12.3) but whose real page
 * lands in a later phase — keeps navigation/routing real end to end
 * without building the feature ahead of its phase. */
export function ComingSoon({ title, description }: ComingSoonProps) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-4 text-center">
      <h1 className="text-xl font-semibold text-text">{title}</h1>
      <p className="mt-2 max-w-sm text-sm text-text-muted">{description}</p>
    </div>
  )
}
