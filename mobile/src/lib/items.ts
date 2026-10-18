// Pictures of each kind of item (Microsoft Fluent Emoji 3D, MIT licence), keyed by the catalog icon.
const PICS: Record<string, number> = {
  phone: require('../../assets/items/phone.png'),
  smartphone: require('../../assets/items/phone.png'),
  bottle: require('../../assets/items/bottle.png'),
  cup: require('../../assets/items/cup.png'),
  keys: require('../../assets/items/keys.png'),
  key: require('../../assets/items/keys.png'),
  wallet: require('../../assets/items/wallet.png'),
  airpods: require('../../assets/items/airpods.png'),
  glasses: require('../../assets/items/glasses.png'),
  laptop: require('../../assets/items/laptop.png'),
  book: require('../../assets/items/book.png'),
  backpack: require('../../assets/items/backpack.png'),
  remote: require('../../assets/items/remote.png'),
  tv: require('../../assets/items/remote.png'),
  mouse: require('../../assets/items/mouse.png'),
  pill: require('../../assets/items/pill.png'),
}

export const itemPic = (icon: string) => PICS[icon] ?? PICS.backpack

// Real photos of the person's own things. Only the glasses have been shot so far, so every item
// shows them until the rest are added here.
const PHOTOS: Record<string, number> = {
  glasses: require('../../assets/items/glasses.png'),
}

export const itemPhoto = (icon: string) => PHOTOS[icon] ?? PHOTOS.glasses
