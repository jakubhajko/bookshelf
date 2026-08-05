import type { InputHTMLAttributes } from 'react'

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  id: string
}

/** Labeled text input built from the design tokens (ADR-0008) — shared by
 * every form (auth today, account/shelf forms later) so focus rings, error
 * states, and spacing stay consistent without each page re-declaring them. */
export function TextField({ label, id, className, ...inputProps }: TextFieldProps) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm text-text-muted">
        {label}
      </label>
      <input
        id={id}
        className={`mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-text focus:outline-none focus:ring-2 focus:ring-accent ${className ?? ''}`}
        {...inputProps}
      />
    </div>
  )
}
