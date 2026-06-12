import { useEffect, useState } from "react";
import { liveScoreStreamUrl } from "../lib/api";

/**
 * Subscribe to /api/live-match-score/{id}/stream over SSE.
 *
 * Returns the latest score payload plus a status flag that the UI uses
 * to render a pulse / offline badge. The connection is closed and torn
 * down on unmount; if the server emits an `end` or `error` event we
 * surface it as `status: "closed"` so the caller can fall back to the
 * single-shot fetch.
 *
 * @param {number|null|undefined} matchId
 * @returns {{score: object|null, status: "idle"|"open"|"closed"}}
 */
export const useLiveScoreStream = (matchId) => {
    const [score, setScore] = useState(null);
    const [status, setStatus] = useState(matchId ? "idle" : "closed");

    useEffect(() => {
        if (!matchId) return undefined;
        const url = liveScoreStreamUrl(matchId);
        let source;
        try {
            source = new EventSource(url, { withCredentials: false });
        } catch {
            setStatus("closed");
            return undefined;
        }
        setStatus("open");

        const handleScore = (event) => {
            try {
                const payload = JSON.parse(event.data);
                if (payload && payload.miniscore) setScore(payload.miniscore);
                else if (payload) setScore(payload);
            } catch {
                // ignore malformed frames
            }
        };
        const handleEnd = () => {
            setStatus("closed");
            source.close();
        };
        source.addEventListener("score", handleScore);
        source.addEventListener("end", handleEnd);
        source.addEventListener("error", handleEnd);
        source.onerror = handleEnd;

        return () => {
            source.removeEventListener("score", handleScore);
            source.removeEventListener("end", handleEnd);
            source.removeEventListener("error", handleEnd);
            source.close();
        };
    }, [matchId]);

    return { score, status };
};

export default useLiveScoreStream;
