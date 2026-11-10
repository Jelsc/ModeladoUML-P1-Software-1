import { useEffect, useState } from "react";
import { request } from "../../api.js";

// Loads the life cycle of one endpoint (sequence of calls, dependencies, suggested tests and the results of the last run).
// `refreshKey` (for example the id of the latest test run) reloads it in place, without flashing the loading state.
export function useMethodFlow(endpointId, refreshKey = null) {
  const [state, setState] = useState({ flow: null, loading: true, error: "" });
  useEffect(() => { setState({ flow: null, loading: true, error: "" }); }, [endpointId]);
  useEffect(() => {
    let alive = true;
    request(`/endpoints/${endpointId}/flow`)
      .then((flow) => { if (alive) setState({ flow, loading: false, error: "" }); })
      .catch((e) => { if (alive) setState({ flow: null, loading: false, error: e.message }); });
    return () => { alive = false; };
  }, [endpointId, refreshKey]);
  return state;
}
