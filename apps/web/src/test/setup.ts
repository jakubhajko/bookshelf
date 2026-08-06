import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// jsdom doesn't implement IntersectionObserver at all (verified directly:
// `typeof window.IntersectionObserver` is `undefined` on a fresh jsdom
// Window) — Home's infinite-scroll effect would throw the moment it mounts
// in a test without this. `observe` is deliberately a no-op stub, not a
// working simulation: infinite-scroll's "sentinel became visible" trigger
// is exercised by Playwright (real browser, real IntersectionObserver) in
// Phase 9, not simulated here.
class MockIntersectionObserver implements IntersectionObserver {
  readonly root = null
  readonly rootMargin = ''
  readonly scrollMargin = ''
  readonly thresholds: ReadonlyArray<number> = []
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
  takeRecords = vi.fn(() => [])
}
vi.stubGlobal('IntersectionObserver', MockIntersectionObserver)

// Node 26's own native, experimental `globalThis.localStorage` shadows
// jsdom's working per-window implementation and throws
// ("localStorage is not available because --localstorage-file was not
// provided") the moment anything touches it — verified directly: a
// standalone jsdom window's `localStorage` works fine, but this project's
// Node version does not, without a CLI flag this repo has no reason to
// require just to run tests. A small in-memory `Storage` stands in for
// both `localStorage` (`Home`'s guidance banner) and `sessionStorage`
// (`useLastUsedShelf`, `useScrollRestoration`) so tests don't depend on
// that flag or on whichever Node version happens to run them.
class MemoryStorage implements Storage {
  #store = new Map<string, string>()
  get length() {
    return this.#store.size
  }
  clear = () => this.#store.clear()
  getItem = (key: string) => this.#store.get(key) ?? null
  key = (index: number) => Array.from(this.#store.keys())[index] ?? null
  removeItem = (key: string) => {
    this.#store.delete(key)
  }
  setItem = (key: string, value: string) => {
    this.#store.set(key, String(value))
  }
}
vi.stubGlobal('localStorage', new MemoryStorage())
vi.stubGlobal('sessionStorage', new MemoryStorage())

// jsdom implements no pointer-capture APIs at all (verified directly:
// `Element.prototype.hasPointerCapture` is `undefined`) — Radix Toast's
// swipe-to-dismiss gesture handling calls these unconditionally the
// moment a pointer event fires on a toast, throwing
// "target.hasPointerCapture is not a function" the instant a test clicks
// anything inside one. Dialog/AlertDialog/Popover never hit this path
// (no swipe gesture), which is why it didn't surface until Phase 9 added
// Toast specifically. No-op stubs are enough: nothing here asserts on
// actual pointer-capture state, only that clicking doesn't throw.
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.setPointerCapture ??= () => {}
Element.prototype.releasePointerCapture ??= () => {}
