import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router'
import { AuthProvider } from './auth/AuthProvider'
import { GuestOnly } from './auth/GuestOnly'
import { RequireAuth } from './auth/RequireAuth'
import { AccountPage } from './routes/Account'
import { BookDetailPage } from './routes/BookDetail'
import { HomePage } from './routes/Home'
import { LoginPage } from './routes/Login'
import { NotFoundPage } from './routes/NotFound'
import { RatedPage } from './routes/Rated'
import { RegisterPage } from './routes/Register'
import { SearchPage } from './routes/Search'
import { ShelfBooksPage } from './routes/ShelfBooks'
import { ShelfDiscoverPage } from './routes/ShelfDiscover'
import { ShelvesPage } from './routes/Shelves'
import { AppShell } from './shell/AppShell'

const queryClient = new QueryClient()

// Every route from spec §12.3 exists now — most render a Phase 7/8
// placeholder (ComingSoon) rather than the real page, so navigation, auth
// guards, and the shell are all real end to end without building features
// ahead of their phase.
export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route element={<GuestOnly />}>
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/login" element={<LoginPage />} />
            </Route>

            <Route element={<RequireAuth />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<HomePage />} />
                <Route path="/search" element={<SearchPage />} />
                <Route path="/books/:bookId" element={<BookDetailPage />} />
                <Route path="/shelves" element={<ShelvesPage />} />
                <Route path="/shelves/:shelfId/books" element={<ShelfBooksPage />} />
                <Route path="/shelves/:shelfId/discover" element={<ShelfDiscoverPage />} />
                <Route path="/rated" element={<RatedPage />} />
                <Route path="/account" element={<AccountPage />} />
              </Route>
            </Route>

            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
