/** Small React hooks over the API client: offline queue state. */
import { useEffect, useState } from "react";

import { OfflineState, subscribeOffline } from "./client";

export function useOfflineState(): OfflineState {
  const [state, setState] = useState<OfflineState>({ pending: [], failure: null, syncing: false });
  useEffect(() => subscribeOffline(setState), []);
  return state;
}
