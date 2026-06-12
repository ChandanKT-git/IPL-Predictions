import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import IPLApp from "@/components/IPLApp";
import { SharedPrediction } from "@/components/SharedPrediction";
import ErrorBoundary from "@/components/ErrorBoundary";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <div className="App">
        <BrowserRouter>
          <ErrorBoundary label="application">
            <Routes>
              <Route path="/" element={<IPLApp />} />
              <Route path="/share/:id" element={<SharedPrediction />} />
            </Routes>
          </ErrorBoundary>
        </BrowserRouter>
      </div>
    </QueryClientProvider>
  );
}

export default App;
