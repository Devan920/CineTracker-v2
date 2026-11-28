import { AlertTriangle, RefreshCw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  resetKey?: string;
  sectionLabel?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, message: "" };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {
      hasError: true,
      message: error?.message || "Unexpected rendering failure.",
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("CineTracker UI ErrorBoundary caught:", error, info.componentStack);
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false, message: "" });
    }
  }

  private handleReloadDashboard = () => {
    this.setState({ hasError: false, message: "" });
    if (window.location.pathname !== "/") {
      window.location.assign("/");
    } else {
      window.location.reload();
    }
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="mx-auto my-8 max-w-xl rounded-2xl border border-rose-500/40 bg-[#12151E] p-6 text-center shadow-2xl"
        >
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-rose-500/30 bg-rose-500/10">
            <AlertTriangle className="h-6 w-6 text-rose-400" />
          </div>
          <h2 className="mt-3 font-display text-lg font-bold text-white">
            {this.props.sectionLabel
              ? `Unable to render ${this.props.sectionLabel}`
              : "Something went wrong rendering this view"}
          </h2>
          <p className="mt-1.5 break-words text-xs text-zinc-400">{this.state.message}</p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2.5">
            <button
              type="button"
              onClick={this.handleReloadDashboard}
              className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl bg-[#F59E0B] px-4 py-2 text-xs font-bold text-black shadow-lg shadow-[#F59E0B]/20 transition hover:bg-amber-400"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Reload Dashboard
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
