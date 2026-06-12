import React from "react";
import { AlertTriangle, RefreshCcw } from "lucide-react";

export class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { error: null };
    }

    static getDerivedStateFromError(error) {
        return { error };
    }

    componentDidCatch(error, info) {
        if (typeof window !== "undefined" && window.console) {
            window.console.error("ErrorBoundary caught:", error, info);
        }
    }

    reset = () => this.setState({ error: null });

    render() {
        if (this.state.error) {
            return (
                <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-6 text-sm text-white/80">
                    <div className="flex items-center gap-2 text-red-400 font-heading uppercase tracking-widest text-xs">
                        <AlertTriangle className="w-4 h-4" />
                        Something broke in {this.props.label || "this section"}
                    </div>
                    <p className="mt-3 text-white/60">
                        {this.state.error.message || "Unexpected error"}
                    </p>
                    <button
                        onClick={this.reset}
                        className="mt-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-md border border-white/15 hover:bg-white/5 text-xs uppercase tracking-widest"
                    >
                        <RefreshCcw className="w-3 h-3" /> Try again
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}

export default ErrorBoundary;
