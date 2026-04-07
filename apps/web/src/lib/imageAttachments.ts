import type { ImageAttachment } from "@talktollm/contracts";

export const acceptedImageMimeTypes = ["image/png", "image/jpeg", "image/webp"] as const;
export const acceptedImageFileInput = acceptedImageMimeTypes.join(",");

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";

  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }

  return window.btoa(binary);
}

async function readImageDimensions(file: Blob): Promise<{ width: number; height: number }> {
  const objectUrl = URL.createObjectURL(file);

  try {
    return await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => {
        resolve({
          width: image.naturalWidth || image.width,
          height: image.naturalHeight || image.height,
        });
      };
      image.onerror = () => reject(new Error("Unable to read screenshot dimensions."));
      image.src = objectUrl;
    });
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

export async function fileToImageAttachment(file: Blob & { type: string; name?: string }): Promise<ImageAttachment> {
  if (!acceptedImageMimeTypes.includes(file.type as (typeof acceptedImageMimeTypes)[number])) {
    throw new Error("Only PNG, JPEG, and WebP screenshots are supported.");
  }

  const [dimensions, arrayBuffer] = await Promise.all([readImageDimensions(file), file.arrayBuffer()]);
  return {
    mimeType: file.type,
    dataBase64: arrayBufferToBase64(arrayBuffer),
    width: dimensions.width,
    height: dimensions.height,
    name: file.name || undefined,
  };
}

export function attachmentToDataUrl(attachment: ImageAttachment): string {
  return `data:${attachment.mimeType};base64,${attachment.dataBase64}`;
}

export function getImageFileFromClipboard(event: ClipboardEvent): File | null {
  const items = event.clipboardData?.items;
  if (!items) {
    return null;
  }

  for (const item of Array.from(items)) {
    if (!item.type.startsWith("image/")) {
      continue;
    }

    const file = item.getAsFile();
    if (file) {
      return file;
    }
  }

  return null;
}
