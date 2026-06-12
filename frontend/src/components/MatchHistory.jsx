import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { recentPredictionsQuery } from "../lib/queries";
import { toggleFavorite } from "../lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { Star, Share2, Clock, MapPin } from "lucide-react";
import { toast } from "sonner";
import { formatDistanceToNow } from "date-fns";

export const MatchHistory = ({ onSelect }) => {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery(recentPredictionsQuery(10));
  const predictions = data ?? [];

  const handleFavorite = async (e, id) => {
    e.stopPropagation();
    try {
      const res = await toggleFavorite(id);
      queryClient.setQueryData(
        ["predictions", "recent", 10],
        (prev) =>
          prev?.map((p) => (p.id === id ? { ...p, is_favorite: res.is_favorite } : p)) ?? prev,
      );
      toast.success(res.is_favorite ? "Added to favorites" : "Removed from favorites");
    } catch {
      toast.error("Action failed");
    }
  };

  const handleShare = (e, id) => {
    e.stopPropagation();
    const url = `${window.location.origin}/share/${id}`;
    navigator.clipboard.writeText(url);
    toast.success("Shareable link copied to clipboard.");
  };

  if (isLoading) return <div className="p-8 text-center text-white/50">Loading history...</div>;
  if (predictions.length === 0) return null;

  return (
    <section className="px-6 py-12 mx-auto max-w-7xl sm:px-8">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-heading uppercase tracking-wider">Recent Predictions</h2>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {predictions.map((p) => (
          <Card
            key={p.id}
            className="bg-white/5 border-white/10 hover:border-[#FF3B30]/50 transition-all cursor-pointer group"
            onClick={() => onSelect(p)}
          >
            <CardHeader className="pb-2">
              <div className="flex justify-between items-start">
                <Badge variant="outline" className="text-[10px] uppercase font-mono border-white/20">
                  {p.output.match_outcome.split(" ")[0]} Favoured
                </Badge>
                <div className="flex gap-2">
                  <button
                    onClick={(e) => handleFavorite(e, p.id)}
                    className={`transition-colors ${p.is_favorite ? "text-yellow-400" : "text-white/20 hover:text-white"
                      }`}
                  >
                    <Star size={16} fill={p.is_favorite ? "currentColor" : "none"} />
                  </button>
                  <button
                    onClick={(e) => handleShare(e, p.id)}
                    className="text-white/20 hover:text-white transition-colors"
                  >
                    <Share2 size={16} />
                  </button>
                </div>
              </div>
              <CardTitle className="text-lg mt-2 flex items-center gap-2">
                <span className="uppercase">{p.input.team_a}</span>
                <span className="text-[#FF3B30]">vs</span>
                <span className="uppercase">{p.input.team_b}</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3 text-sm text-white/60">
                <div className="flex items-center gap-2">
                  <Clock size={14} />
                  <span>
                    {formatDistanceToNow(new Date(p.created_at), { addSuffix: true })}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <MapPin size={14} />
                  <span className="capitalize">{p.input.venue.replace("_", " ")}</span>
                </div>
                <div className="pt-2 border-t border-white/5">
                  <div className="flex justify-between items-center">
                    <span>Projected Score:</span>
                    <span className="text-white font-bold">{p.output.predicted_score}</span>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
};
