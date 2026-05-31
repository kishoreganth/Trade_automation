"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex items-center justify-center p-8">
      <div className="text-center max-w-md">
        <h2 className="text-lg font-bold text-gray-900 mb-2">Page Error</h2>
        <p className="text-sm text-gray-600 mb-4">
          {error.message || "Failed to load this page."}
        </p>
        <button
          onClick={reset}
          className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90"
        >
          Retry
        </button>
      </div>
    </div>
  );
}
