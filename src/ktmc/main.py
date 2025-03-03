import bittensor as bt
import logging
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Bot:
    def __init__(self, wallet, subtensor, netuid=8, stake_amount=0.5):
        self.wallet = wallet
        self.subtensor = subtensor
        self.netuid = netuid
        self.stake_amount = stake_amount
    
    async def wait_epoch(self):
        q_tempo = [v for (k, v) in self.subtensor.query_map_subtensor("Tempo") if k == self.netuid]
        if len(q_tempo) == 0:
            raise Exception("could not determine tempo")
        tempo = q_tempo[0].value
        logging.info(f"tempo = {tempo}")

        await self.wait_interval(tempo)

    def next_tempo(self, current_block: int, tempo: int) -> int:
        interval = tempo + 1
        last_epoch = current_block - 1 - (current_block + self.netuid + 1) % interval
        next_tempo_ = last_epoch + interval
        return next_tempo_

    async def wait_interval(self, tempo):
        reporting_interval: int = 1
        current_block = self.subtensor.get_current_block()
        next_tempo_block_start = self.next_tempo(current_block, tempo)
        last_reported = None

        while current_block < next_tempo_block_start:
            await asyncio.sleep(0.25)
            current_block = self.subtensor.get_current_block()

            if last_reported is None or current_block - last_reported >= reporting_interval:
                last_reported = current_block
                print(
                    f"Current Block: {current_block}  Next tempo for netuid {self.netuid} at: {next_tempo_block_start}"
                )
                logging.info(
                    f"Current Block: {current_block}  Next tempo for netuid {self.netuid} at: {next_tempo_block_start}"
                )

    async def execute_strategy(self):
        try:
            # Wait for next epoch
            await self.wait_epoch()

            # Get next tempo block
            current_block = self.subtensor.get_current_block()
            tempo_result = [v for (k, v) in self.subtensor.query_map_subtensor("Tempo") if k == self.netuid]
            tempo = tempo_result[0].value
            next_epoch_block = self.next_tempo(current_block, tempo)

            # LeStakeBefore
            stake_at_block = next_epoch_block - 3

            # LeWait
            while current_block < stake_at_block:
                await asyncio.sleep(0.25)
                current_block = self.subtensor.get_current_block()

            # LeConvert
            stake_amount_rao = int(self.stake_amount * 10**9)

            logger.info(f"Staking {self.stake_amount} TAO to subnet {self.netuid} at block {current_block}")

            # LeStake
            self.subtensor.add_stake(
                wallet=self.wallet,
                hotkey=self.wallet.get_hotkey(),
                amount=stake_amount_rao
            )

            logger.info(f"Successfully staked to subnet {self.netuid}")
            
            unstake_at_block = next_epoch_block + 1
            
            current_block = self.subtensor.get_current_block()
            while current_block < unstake_at_block:
                await asyncio.sleep(0.25)
                current_block = self.subtensor.get_current_block()
            
            logger.info(f"Unstaking from subnet {self.netuid} at block {current_block}")

            # LeUnstake
            self.subtensor.unstake(
                wallet=self.wallet,
                hotkey=self.wallet.get_hotkey(),
                amount=stake_amount_rao
            )
            
            logger.info(f"Successfully unstaked from subnet {self.netuid}")
            
            return True
        except Exception as e:
            logger.error(f"Error executing MEV strategy: {e}")
            return False

async def run_continously():
    wallet = bt.wallet(name='default')
    subtensor = bt.subtensor(network="finney")

    bot = Bot(wallet, subtensor, netuid=8, stake_amount=0.5)

    while True:
        try:
            await bot.execute_strategy()

        except Exception as e:
            logger.error(f"Error in Bot loop: {e}")
            await asyncio.sleep(60)


def main():
    try:
        asyncio.run(run_continously())

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Error in main: {e}")
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
