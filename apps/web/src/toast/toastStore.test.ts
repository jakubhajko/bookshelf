import { beforeEach, describe, expect, it, vi } from 'vitest'
import { dismissToast, getToastSnapshot, showToast, subscribeToasts } from './toastStore'

describe('toastStore', () => {
  beforeEach(() => {
    for (const toast of getToastSnapshot()) dismissToast(toast.id)
  })

  it('starts empty', () => {
    expect(getToastSnapshot()).toEqual([])
  })

  it('adds a toast with the given title and variant', () => {
    showToast('Saved successfully', 'success')

    const [toast] = getToastSnapshot()
    expect(toast).toMatchObject({ title: 'Saved successfully', variant: 'success' })
  })

  it('defaults to the info variant', () => {
    showToast('Just so you know')

    expect(getToastSnapshot()[0]?.variant).toBe('info')
  })

  it('supports multiple concurrent toasts', () => {
    showToast('First')
    showToast('Second')

    expect(getToastSnapshot()).toHaveLength(2)
  })

  it('dismissToast removes only the matching toast', () => {
    showToast('Keep me')
    showToast('Remove me')
    const idToRemove = getToastSnapshot()[1]?.id

    dismissToast(idToRemove ?? '')

    expect(getToastSnapshot()).toHaveLength(1)
    expect(getToastSnapshot()[0]?.title).toBe('Keep me')
  })

  it('notifies subscribers on every change', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeToasts(listener)

    showToast('Hello')
    expect(listener).toHaveBeenCalledTimes(1)

    dismissToast(getToastSnapshot()[0]?.id ?? '')
    expect(listener).toHaveBeenCalledTimes(2)

    unsubscribe()
    showToast('Should not notify')
    expect(listener).toHaveBeenCalledTimes(2)
  })
})
