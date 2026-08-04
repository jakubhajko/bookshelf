import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router'
import { HomePage } from './routes/Home'

// Real routes (/register, /login, /search, /books/:bookId, /shelves, ...,
// spec §12.3) are added as their phases land (6-8). Registering unbuilt
// routes now would be a disconnected stub, not a vertical slice.
const queryClient = new QueryClient()

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
