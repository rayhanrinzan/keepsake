// Photos of each kind of item, keyed by the catalog icon. Anything without its own photo yet shows
// the backpack.
const PHOTOS: Record<string, number> = {
  glasses: require('../../assets/items/glasses.png'),
  phone: require('../../assets/items/iphone.png'),
  smartphone: require('../../assets/items/iphone.png'),
  keys: require('../../assets/items/key.png'),
  key: require('../../assets/items/key.png'),
  wallet: require('../../assets/items/wallet.png'),
  bottle: require('../../assets/items/waterbottle.png'),
  airpods: require('../../assets/items/airpods.png'),
  backpack: require('../../assets/items/backpack.png'),
}

export const itemPhoto = (icon: string) => PHOTOS[icon] ?? PHOTOS.backpack
export const itemPic = itemPhoto
