import { Component, type ErrorInfo, type ReactNode } from "react";
import { Link } from "react-router-dom";

export class RouteErrorBoundary extends Component<{children: ReactNode}, {error: Error | null}> {
  state = {error: null as Error | null};
  static getDerivedStateFromError(error: Error) {return {error};}
  componentDidCatch(error: Error, info: ErrorInfo) {console.error("QwenSci route error", error, info);}
  render() {return this.state.error ? <div className="route-error"><span className="eyebrow">WORKSPACE RECOVERY</span><h1>页面暂时无法显示</h1><p>{this.state.error.message}</p><Link className="button primary" to="/app">返回工作区</Link></div> : this.props.children;}
}
