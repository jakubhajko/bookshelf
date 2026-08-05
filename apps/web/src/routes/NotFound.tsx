import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 text-center">
      <h1 className="text-xl font-semibold text-text">Page not found</h1>
      <p className="mt-4 text-sm">
        <Link to="/" className="text-accent hover:underline">
          Go back home
        </Link>
      </p>
    </div>
  )
}
