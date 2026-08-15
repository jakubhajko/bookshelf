import { QueryClientProvider } from '@tanstack/react-query'
import { ErrorBoundary } from 'react-error-boundary'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router'
import { queryClient } from './api/queryClient'
import { AuthProvider } from './auth/AuthProvider'
import { GuestOnly } from './auth/GuestOnly'
import { RequireAuth } from './auth/RequireAuth'
import { RootErrorFallback } from './components/ErrorFallback'
import type { ModalLocationState } from './routing/modalNavigation'
import { AccountPage } from './routes/Account'
import { BookDetailPage } from './routes/BookDetail'
import { BookDetailModal } from './routes/BookDetailModal'
import { HomePage } from './routes/Home'
import { LoginPage } from './routes/Login'
import { NotFoundPage } from './routes/NotFound'
import { RatedPage } from './routes/Rated'
import { OnboardingPage } from './routes/Onboarding'
import { RegisterPage } from './routes/Register'
import { SearchPage } from './routes/Search'
import { ShelfBooksPage } from './routes/ShelfBooks'
import { ShelfDetailLayout } from './routes/ShelfDetailLayout'
import { ShelfLensPage } from './routes/ShelfLens'
import { ShelvesPage } from './routes/Shelves'
import { AppShell } from './shell/AppShell'
import { ToastViewport } from './toast/ToastViewport'

/**
 * Route-backed modal pattern (spec §12.7). When a card navigates to
 * `/books/:bookId` with `state.backgroundLocation` set (see
 * `routing/modalNavigation.ts`), the *first* `<Routes>` below renders
 * against that background location — so the page underneath (e.g. Home)
 * stays mounted, preserving its scroll position for free — while a
 * *second* `<Routes>`, using the real current location, renders just the
 * modal on top of it. Direct navigation (no `backgroundLocation` in state:
 * a fresh page load, a shared link, a reload) has nothing to render a
 * background from, so only the first `<Routes>` matches and
 * `/books/:bookId` renders as the plain full-page route instead.
 */
export function AppRoutes() {
  const location = useLocation()
  const state = location.state as ModalLocationState | null
  const backgroundLocation = state?.backgroundLocation

  return (
    <>
      <Routes location={backgroundLocation ?? location}>
        <Route element={<GuestOnly />}>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/login" element={<LoginPage />} />
        </Route>

        <Route element={<RequireAuth />}>
          {/* Outside `AppShell` on purpose: onboarding is a full-page
            * first-run task, and the sidebar's Home/Shelves/Rated links
            * would invite the reader to wander off mid-task without the
            * page having said what skipping does. "Skip for now" is the
            * way out, and it is always available. */}
          <Route path="/welcome" element={<OnboardingPage />} />
          <Route element={<AppShell />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/books/:bookId" element={<BookDetailPage />} />
            <Route path="/shelves" element={<ShelvesPage />} />
            {/* The lens view sits outside `ShelfDetailLayout`: it carries
              * the feed's own chrome (lens row, shelf header, "View
              * shelf") rather than the shelf page's rename/delete header,
              * so the two no longer share a layout. */}
            <Route path="/shelves/:shelfId/discover" element={<ShelfLensPage />} />
            <Route path="/shelves/:shelfId" element={<ShelfDetailLayout />}>
              <Route path="books" element={<ShelfBooksPage />} />
            </Route>
            <Route path="/rated" element={<RatedPage />} />
            <Route path="/account" element={<AccountPage />} />
          </Route>
        </Route>

        <Route path="*" element={<NotFoundPage />} />
      </Routes>

      {backgroundLocation && (
        <Routes>
          <Route element={<RequireAuth />}>
            <Route path="/books/:bookId" element={<BookDetailModal />} />
          </Route>
        </Routes>
      )}
    </>
  )
}

export function App() {
  return (
    <ErrorBoundary FallbackComponent={RootErrorFallback}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <AppRoutes />
          </AuthProvider>
        </BrowserRouter>
        <ToastViewport />
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
