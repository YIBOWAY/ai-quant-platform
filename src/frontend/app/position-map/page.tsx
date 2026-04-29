import { Map, Layers } from "lucide-react";
import { getSymbols } from "@/lib/api";

export default async function PositionMapPage() {
  const symbols = await getSymbols();

  return (
    <div className="flex-1 flex flex-col items-center justify-center h-full min-h-[50vh] text-zinc-400">
      <Layers size={48} className="mb-4 text-zinc-600" />
      <h2 className="text-xl font-semibold mb-2 font-sans tracking-tight text-zinc-200">Position Map</h2>
      <p className="text-sm font-sans max-w-md text-center">
        Available local symbols from the API: {symbols.symbols.join(", ")}.
        This view remains a visualization placeholder until portfolio maps are added.
      </p>
    </div>
  );
}
