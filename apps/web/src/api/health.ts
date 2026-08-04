import { apiFetch } from './client'

export interface HealthStatus {
  status: string
}

export function fetchLiveness(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>('/api/v1/health/live')
}
