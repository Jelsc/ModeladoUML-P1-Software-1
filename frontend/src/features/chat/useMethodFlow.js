import { useEffect, useState } from "react";
import { request } from "../../api.js";

// Loads the life cycle of one endpoint (sequence of calls, dependencies, suggested tests).
export function useMethodFlow(endpointId) {
  const [state, setState] = useState({ flow: null, loading: true, error: "" });
  useEffect(() => {
    let alive = true;
    setState({ flow: null, loading: true, error: "" });
    request(`/endpoints/${endpointId}/flow`)
      .then((flow) => { if (alive) setState({ flow, loading: false, error: "" }); })
      .catch((e) => { if (alive) setState({ flow: null, loading: false, error: e.message }); });
    return () => { alive = false; };
  }, [endpointId]);
  return state;
}
