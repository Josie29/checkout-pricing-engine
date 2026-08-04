/**
 * Hand-rolled history-API routing — no router dependency. Two routes:
 * the shop (`/`) and the checkout (`/checkout`); unknown paths fall back
 * to the shop.
 */
import { useCallback, useEffect, useState } from 'react'

export type Route = 'shop' | 'checkout'

/** Path each route is pushed to the history as. */
export const ROUTE_PATHS: Record<Route, string> = {
  shop: '/',
  checkout: '/checkout',
}

/**
 * Map a location pathname to a route. Unknown paths render the shop.
 *
 * @param pathname - `window.location.pathname`.
 * @returns The matching route.
 */
export function pathToRoute(pathname: string): Route {
  return pathname === ROUTE_PATHS.checkout ? 'checkout' : 'shop'
}

/**
 * Current route plus a navigate function. Navigation calls
 * `history.pushState`, and a `popstate` listener keeps the route in sync
 * with the browser's back/forward buttons.
 *
 * @returns The active route and a function to navigate to another one.
 */
export function useRoute(): {
  route: Route
  navigate: (route: Route) => void
} {
  const [route, setRoute] = useState<Route>(() =>
    pathToRoute(window.location.pathname),
  )

  useEffect(() => {
    const onPopState = () => {
      setRoute(pathToRoute(window.location.pathname))
    }
    window.addEventListener('popstate', onPopState)
    return () => {
      window.removeEventListener('popstate', onPopState)
    }
  }, [])

  const navigate = useCallback((next: Route) => {
    window.history.pushState(null, '', ROUTE_PATHS[next])
    setRoute(next)
  }, [])

  return { route, navigate }
}
