import { useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";

const OUTPUT_WIDTH = 900;
const OUTPUT_HEIGHT = 1200;

type Position = { x: number; y: number };

function placement(image: HTMLImageElement, zoom: number, position: Position) {
  const scale = Math.max(OUTPUT_WIDTH / image.naturalWidth, OUTPUT_HEIGHT / image.naturalHeight) * zoom;
  const width = image.naturalWidth * scale;
  const height = image.naturalHeight * scale;
  const maxX = Math.max(0, (width - OUTPUT_WIDTH) / 2);
  const maxY = Math.max(0, (height - OUTPUT_HEIGHT) / 2);
  const x = Math.max(-maxX, Math.min(maxX, position.x));
  const y = Math.max(-maxY, Math.min(maxY, position.y));
  return { width, height, x, y };
}

function drawCrop(canvas: HTMLCanvasElement, image: HTMLImageElement, zoom: number, position: Position) {
  const context = canvas.getContext("2d");
  if (!context) return;
  const placed = placement(image, zoom, position);
  context.clearRect(0, 0, OUTPUT_WIDTH, OUTPUT_HEIGHT);
  context.drawImage(
    image,
    (OUTPUT_WIDTH - placed.width) / 2 + placed.x,
    (OUTPUT_HEIGHT - placed.height) / 2 + placed.y,
    placed.width,
    placed.height,
  );
}

export function ImageCropper({ file, onCancel, onConfirm }: {
  file: File;
  onCancel: () => void;
  onConfirm: (file: File) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragRef = useRef<{ pointerX: number; pointerY: number; position: Position } | undefined>(undefined);
  const [image, setImage] = useState<HTMLImageElement>();
  const [zoom, setZoom] = useState(1);
  const [position, setPosition] = useState<Position>({ x: 0, y: 0 });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    const next = new Image();
    next.onload = () => setImage(next);
    next.src = url;
    setZoom(1);
    setPosition({ x: 0, y: 0 });
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!image || !canvasRef.current) return;
    const placed = placement(image, zoom, position);
    if (placed.x !== position.x || placed.y !== position.y) {
      setPosition({ x: placed.x, y: placed.y });
      return;
    }
    drawCrop(canvasRef.current, image, zoom, position);
  }, [image, position, zoom]);

  function startDrag(event: PointerEvent<HTMLCanvasElement>) {
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { pointerX: event.clientX, pointerY: event.clientY, position };
  }

  function drag(event: PointerEvent<HTMLCanvasElement>) {
    const start = dragRef.current;
    const canvas = canvasRef.current;
    if (!start || !canvas || !image) return;
    const rect = canvas.getBoundingClientRect();
    const next = {
      x: start.position.x + (event.clientX - start.pointerX) * (OUTPUT_WIDTH / rect.width),
      y: start.position.y + (event.clientY - start.pointerY) * (OUTPUT_HEIGHT / rect.height),
    };
    const placed = placement(image, zoom, next);
    setPosition({ x: placed.x, y: placed.y });
  }

  function finishDrag(event: PointerEvent<HTMLCanvasElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    dragRef.current = undefined;
  }

  async function confirm() {
    const canvas = canvasRef.current;
    if (!canvas || !image) return;
    setSaving(true);
    drawCrop(canvas, image, zoom, position);
    const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, "image/webp", 0.92));
    setSaving(false);
    if (!blob) return;
    const baseName = file.name.replace(/\.[^.]+$/, "") || "card";
    onConfirm(new File([blob], `${baseName}.webp`, { type: "image/webp" }));
  }

  return <div className="crop-modal" role="dialog" aria-modal="true" aria-labelledby="crop-title">
    <div className="crop-dialog">
      <div className="crop-heading"><div><p className="eyebrow">CARD ART</p><h2 id="crop-title">이미지 자르기</h2></div><button className="crop-close" onClick={onCancel} aria-label="닫기">×</button></div>
      <p className="crop-help">이미지를 드래그하고 확대해 3:4 카드 영역을 맞춰주세요.</p>
      <div className="crop-stage"><canvas ref={canvasRef} width={OUTPUT_WIDTH} height={OUTPUT_HEIGHT} onPointerDown={startDrag} onPointerMove={drag} onPointerUp={finishDrag} onPointerCancel={finishDrag} /></div>
      <label className="crop-zoom"><span>확대</span><input type="range" min="1" max="3" step="0.01" value={zoom} onChange={event => setZoom(Number(event.target.value))} /><b>{Math.round(zoom * 100)}%</b></label>
      <div className="crop-actions"><button onClick={onCancel}>취소</button><button className="primary-button" disabled={!image || saving} onClick={confirm}>{saving ? "처리 중…" : "이 영역 사용"}</button></div>
    </div>
  </div>;
}
