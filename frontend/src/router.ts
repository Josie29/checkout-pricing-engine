/**
 * Hand-rolled history-API routing — no router dependency. Three routes:
 * the shop (`/`), the checkout (`/checkout`), and the promotion-authoring
 * admin page (`/admin`); unknown paths fall back to the shop.
 */
import { useCallback, useEffect, useState } from 'react'

export type Route = 'shop' | 'checkout' | 'admin'

/** Path each route is pushed to the history as. */
export const ROUTE_PATHS: Record<Route, string> = {
  shop: '/',
  checkout: '/checkout',
  admin: '/admin',
}

/**
 * Map a location pathname to a route. Unknown paths render the shop.
 *
 * @param pathname - `window.location.pathname`.
 * @returns The matching route.
 */
export function pathToRoute(pathname: string): Route {
  if (pathname === ROUTE_PATHS.checkout) {
    return 'checkout'
  }
  if (pathname === ROUTE_PATHS.admin) {
    return 'admin'
  }
  return 'shop'
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
